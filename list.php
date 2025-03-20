<?php
//include("index.html");
//$nav=2;
// Connect to the MySQL database
$conn = mysqli_connect('localhost','MSBABlog','44C#atlantic','MSBABlog');

// Check the connection
if (!$conn) {
    die("Connection failed: " . mysqli_connect_error());
}

// Retrieve data from the database
$sql = "SELECT id, citation, snippet, filed_date, parties, date_added, reviewed, assignment, court, URL, cited_from, cite_count FROM tbscrapedata where snippet is not null and assignment<>23 and reviewed=0 order by parties, date_added DESC;";
$result = mysqli_query($conn, $sql);



$sql="select id, editorname, editoremail from editors where editorstatus='Active' order by editorname;";
$editors = mysqli_query($conn, $sql);

// Build the HTML table
if (mysqli_num_rows($result) > 0) {

    echo "<table><thead>";
    echo "<tr align='center'>";
    echo "<th valign='center'>Case</th>";
    echo "<th valign='center'>Cite</th>";
    echo "<th valign='center'>Snippet</th>";
    echo "<th valign='center'>Review Status</th>";
    echo "<th valign='center'>Assigned Editor</th>";

    echo "</tr></thead>";

    while ($row = mysqli_fetch_assoc($result)) {
        $wherefrom=$row['cited_from'];
        $assign=$row["assignment"];

        echo "<tr>";
        echo "<td valign='center'><a href='" . $row["URL"] . "' target='_blank'>" . $row["parties"] . "</a></td>";
        echo "<td valign='center'>" . $row["citation"] . "</td>";
        echo "<td valign='center'>" . $row["snippet"] . "</td>";

        // Add more columns as needed

        // Form for updating data
        echo "<td width='150' valign='center'>";
        echo "<form method='POST' action='index.php'>";
        echo "<input type='hidden' name='record_id' value='" . $row["id"] . "'>";
        echo "<input type='hidden' name='nav' value='20'>";
        echo "<select name='reviewstatus'>";
        echo "<option value=1 " . ($row["reviewed"] == '1' ? "selected" : "") . ">Reviewed</option>";
        echo "<option value=0 " . ($row["reviewed"] == '0' ? "selected" : "") . ">Unreviewed</option>";
        echo "</select>";
        echo "</td>";
        echo "<td width='150' valign='center'>";
        echo "<select name='editorvalue'>";
        foreach ($editors as $editor) {
            $optionId = $editor["id"];
            $optionLabel = $editor["editorname"];

            if($assign == $optionId){ $selected="selected"; } else {$selected="";}

            echo "<option value='$optionId' $selected>$optionLabel</option>";

            //echo $selected. " ".$row["assignment"]. " " .$editor["editorname"]. " ". $editor["id"] ."<br>";

        }
        echo "</select>";
        echo "</td>";
        echo "<td valign='center'>";
        echo "<input type='submit' value='Update'>";
        echo "</form>";
        echo "</td>";
        echo "</tr>";

        if($wherefrom) {
          $sql="select parties, citation, URL from tbScrapeData where id=$wherefrom;";
          //print($sql);
          $priorcites = $conn->query( $sql );
          $priorcite=mysqli_fetch_assoc($priorcites);

          $row_cnt = $priorcites -> num_rows;
          if ($row_cnt>0) {
            $pc=$priorcite['parties'];
            $thecite=$priorcite['citation'];
            $thisURL=$priorcite['URL'];

            echo "<tr>";
            echo "<td align='right'><b>cited by:</b></td>";
            echo "<td><i>$pc</i></td>";
            echo "<td><p>$thecite <a href='$thisURL' target='_blank'>link to case</a></td>";
            echo "<td></td>";
            echo "<td></td>";
            echo "<td></td>";
            echo "</tr>";
          }
        }
    }
    echo "</table>";
    echo "<p>A total of ". mysqli_num_rows($result)." records were returned.<br>";
} else {
    echo "<p>No data found.";
}



// Close
?>
