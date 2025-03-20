<?php
include("index.html");

if($_SERVER["REQUEST_METHOD"] == "GET") {

  if($_GET['nav']==0) {
    $conn = mysqli_connect('localhost','MSBABlog','44C#atlantic','MSBABlog');
    $sql = "select editorname, year(date_added) as EntryYear, count(*) as Recs from tbscrapedata inner join editors on tbscrapedata.assignment=editors.id group by editorname, year(date_added) order by year(date_added),editorname;";
    $result = mysqli_query($conn, $sql);

    echo "<table><thead>";
    echo "<tr><th>Editor Name</th><th>Entry Year</th><th>Entries Assigned</th></thead></tr>";
    foreach ($result as $e) {
        $editorName = $e["editorname"];
        $yr=$e["EntryYear"];
        $count = $e["Recs"];
        echo "<tr><td>".$editorName."</td><td>".$yr."</td><td>".$count."</td></tr>";
    }
    echo "</table>";

  }
  elseif($_GET['nav']==1) {
    $pythonScript = escapeshellcmd('/Users/timfaith/sites/bin/combined_MD_queries.py');
    $pythonPath = escapeshellcmd('/opt/homebrew/bin/python3.12');
    $command = "$pythonPath $pythonScript";
    //echo "<p>Command: $command</p>";

    $output = [];
    $returnValue = 0;
    exec($command,$output,$returnValue);

    //echo "<pre>" . print_r($output, true) . "</pre>";

    // Display any errors or output
    if ($returnValue !== 0) {
        echo "<p>Error executing Python script. Return value: $returnValue</p>";
        echo "<p>Output: " . implode("\n", $output) . "</p>";
    } else {
        echo "<p>Successfully processed Maryland appellate cases.</p>";
    }

    $pythonScript = escapeshellcmd('/Users/timfaith/sites/bin/combined_USDC_queries.py');
    $pythonPath = escapeshellcmd('/opt/homebrew/bin/python3.12');
    $command = "$pythonPath $pythonScript";
    //echo "<p>Command: $command</p>";

    $output = [];
    $returnValue = 0;
    exec($command,$output,$returnValue);

    // Display any errors or output
    if ($returnValue !== 0) {
        echo "<p>Error executing Python script. Return value: $returnValue";
    } else {
        #echo "Output: " . implode("\n", $outputArray);
        echo "<p>Successfully processed Maryland USDC cases.";
    }

    $pythonScript = escapeshellcmd('/Users/timfaith/sites/bin/combined_4thCir_queries.py');
    $pythonPath = escapeshellcmd('/opt/homebrew/bin/python3.12');
    $command = "$pythonPath $pythonScript";
    //echo "<p>Command: $command</p>";

    $output = [];
    $returnValue = 0;
    exec($command,$output,$returnValue);

    // Display any errors or output
    if ($returnValue !== 0) {
        echo "<p>Error executing Python script. Return value: $returnValue";
    } else {
        #echo "Output: " . implode("\n", $outputArray);
        echo "<p>Successfully processed 4th Circuit cases.";
    }

    $pythonScript = escapeshellcmd('/Users/timfaith/sites/bin/SERA_update_from_cites.py');
    $pythonPath = escapeshellcmd('/opt/homebrew/bin/python3.12');
    $command = "$pythonPath $pythonScript";
    //echo "<p>Command: $command</p>";

    $output = [];
    $returnValue = 0;
    exec($command,$output,$returnValue);

    // Display any errors or output
    if ($returnValue !== 0) {
        echo "<p>Error executing Python script. Return value: $returnValue";
    } else {
        #echo "Output: " . implode("\n", $outputArray);
        echo "<p>Successfully refreshed recent cases citing to a previously entry posted to the blog.";
    }


      }
      elseif($_GET['nav']==2) {

        require("list.php");


      }
        elseif($_GET['nav']==3) {

          require("edits.php");


        }
        elseif($_GET['nav']==4) {

          $pythonScript = escapeshellcmd('/Users/timfaith/sites/bin/backup.py');
          $command = escapeshellcmd('/usr/local/Cellar/python@3.11/3.11.6_1/Frameworks/Python.framework/Versions/3.11/bin/python3.11 ') . $pythonScript;
          //echo $command;

          $output = exec($command, $outputArray, $returnValue);

          // Display any errors or output
          if ($returnValue !== 0) {
              echo "Error executing Python script. Return value: $returnValue";
          } else {
              #echo "Output: " . implode("\n", $outputArray);
              echo "<p>Successfully backed up database to subfolder /backups.";
          }

        }
        elseif($_GET['nav']==5) {

          require("fairuse.php");

        }
}
if($_SERVER["REQUEST_METHOD"] == "POST") {
  $conn = mysqli_connect('localhost','MSBABlog','44C#atlantic','MSBABlog');

  // Check the connection
  if (!$conn) {
      die("Connection failed: " . mysqli_connect_error());
  }

        if($_POST['nav']==20) {

            // Handle form submission
            if ($_SERVER["REQUEST_METHOD"] == "POST") {
                $recordId = $_POST["record_id"];
                $updatedValue = $_POST["reviewstatus"];
                $newEditor= $_POST["editorvalue"];

                // Construct the SQL query to update the record
                $sqlUpdate = "UPDATE tbscrapedata SET reviewed=$updatedValue, assignment='$newEditor' WHERE id='$recordId'";
                //echo $sqlUpdate;

                if (mysqli_query($conn, $sqlUpdate)) {
                    echo "Record #".$recordId." updated successfully.";
                } else {

                    echo "Error updating record: " . mysqli_error($conn);
                }
            }
            require("list.php");
          }
          elseif($_POST['nav']==30) {

            // Handle form submission
            if ($_SERVER["REQUEST_METHOD"] == "POST") {
                $recordId = $_POST["record_id"];
                //$updatedValue = $_POST["reviewstatus"];
                $newEditor= $_POST["editorvalue"];
                $newNotes=$_POST["NotesOnAssignment"];
                $newPosted=$_POST["Entry_Posted"];

                if($newPosted=="") {
                  $newP=0;
                } else { $newP=1; }

                // Construct the SQL query to update the record
                $sqlUpdate = "UPDATE tbscrapedata SET assignment='$newEditor', Entry_Posted=$newP, NotesOnAssignment='$newNotes' WHERE id='$recordId'";
                //echo $sqlUpdate;

                if (mysqli_query($conn, $sqlUpdate)) {
                    echo "Record #".$recordId." updated successfully.";
                } else {

                    echo "Error updating record: " . mysqli_error($conn);
                }
            }
            require("edits.php");
          }
          elseif($_POST['nav']==50) {

            // Handle form submission
            if ($_SERVER["REQUEST_METHOD"] == "POST") {
                $recordId = $_POST["record_id"];
                //$updatedValue = $_POST["reviewstatus"];
                $fr=$_POST['fair_user'];
                $rev= $_POST["reviewed"];
                $prev=$_POST["who_prevailed"];
                $sm=$_POST["subject_matter"];

                if($rev=="") {
                  $newR=0;
                } else { $newR=$rev; }

                // Construct the SQL query to update the record
                $sqlUpdate = "UPDATE tbGoogleData SET reviewed=$newR, fair_user='$fr', who_prevailed='$prev', subject_matter=$sm WHERE id='$recordId'";
                //echo $sqlUpdate;

                if (mysqli_query($conn, $sqlUpdate)) {
                    echo "Record #".$recordId." updated successfully.";
                } else {

                    echo "Error updating record: " . mysqli_error($conn);
                }
            }

            require("fairuse.php");
          }



}

?>
