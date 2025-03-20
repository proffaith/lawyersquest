<?php
include("index.html");


if($_SERVER["REQUEST_METHOD"] == "GET") {

  // Connect to the MySQL database
  $conn = mysqli_connect('localhost','Research','44C#atlantic','CCBC');

  $sql = "select oer_text_description, count(*) as theCount from mngt140cases C inner join tboertext L on L.text_id=C.oer_text where cites_to=0 group by oer_text_description;";
  $original_case_counts = mysqli_query($conn, $sql);

  $sql = "select subject_matter_keywords, count(*) as theCount from mngt140cases C inner join tboertext L on L.text_id=C.oer_text where cites_to=0 group by subject_matter_keywords order by subject_matter_keywords;";
  $found_cases = mysqli_query($conn, $sql);

  require("head.php");

  // Check the connection
  if (!$conn) {
      die("Connection failed: " . mysqli_connect_error());
  }



  if($_GET['nav']==0 or !isset($_GET['nav'])) {
    // Retrieve data from the database
    $sql = "select id, parties, citation, subject_matter_keywords, URL, cites_to, snippet, reviewed from mngt140cases order by subject_matter_keywords, parties;";
    $result = mysqli_query($conn, $sql);



    require("list.php");

  }

  elseif($_GET['nav']==1) {
    // Retrieve data from the database
    $sql = "select id, parties, citation, subject_matter_keywords, URL, cites_to, snippet, reviewed from mngt140cases where cites_to=0 and OER_text=1 order by subject_matter_keywords, parties;";
    $result = mysqli_query($conn, $sql);

    require("list.php");

  }

  elseif($_GET['nav']==2) {
    // Retrieve data from the database
    $sql = "select id, parties, citation, subject_matter_keywords, URL, cites_to, snippet, reviewed from mngt140cases where cites_to>0 and citation like 'Dist. Court%' and reviewed=0 order by subject_matter_keywords, parties;";
    $result = mysqli_query($conn, $sql);

    require("list.php");

  }
  elseif($_GET['nav']==3) {
    // Retrieve data from the database
    $sql = "select id, parties, citation, subject_matter_keywords, URL, cites_to, snippet , reviewed from mngt140cases where cites_to>0 and citation not like 'Dist. Court%' and reviewed=0 order by subject_matter_keywords, parties;";
    $result = mysqli_query($conn, $sql);

    require("list.php");

  }
  elseif($_GET['nav']==4) {
    // Retrieve data from the database
    $sql = "select id, parties, citation, subject_matter_keywords, URL, cites_to, snippet, reviewed from mngt140cases where cites_to>0 and citation like 'Supreme Court%' and reviewed=0 order by subject_matter_keywords, parties;";
    $result = mysqli_query($conn, $sql);

    require("list.php");

  }
  elseif($_GET['nav']==5) {
    // Retrieve data from the database
    $sql = "select id, parties, citation, subject_matter_keywords, URL, cites_to, snippet, reviewed from mngt140cases where cites_to=0 and OER_text=2 order by subject_matter_keywords, parties;";
    $result = mysqli_query($conn, $sql);

    require("list.php");

  }
  elseif($_GET['nav']==6) {
    // Retrieve data from the database
    $sql = "select id, parties, citation, subject_matter_keywords, URL, cites_to, snippet, reviewed from mngt140cases where cites_to=0 and OER_text=3 order by subject_matter_keywords, parties;";
    $result = mysqli_query($conn, $sql);

    require("list.php");

  }
}

if($_SERVER["REQUEST_METHOD"] == "POST") {
  $conn = mysqli_connect('localhost','Research','44C#atlantic','CCBC');

  // Check the connection
  if (!$conn) {
      die("Connection failed: " . mysqli_connect_error());
  }

    if($_POST['nav']==10) {

        // Handle form submission
        if ($_SERVER["REQUEST_METHOD"] == "POST") {
            $dataID = $_POST["record_id"];
            $reviewstatus = $_POST["reviewstatus"];
            $return_to = $_POST["return_to"];

            $sqlUpdate="UPDATE mngt140cases SET ";
            $sqlUpdate.="reviewed=$reviewstatus ";
            $sqlUpdate.= " WHERE id=$dataID";
            //echo $sqlUpdate;

            if (mysqli_query($conn, $sqlUpdate)) {
                echo "Record #".$dataID." updated successfully.";
                header("Location: index.php?nav=$return_to");
                exit();
            } else {

                echo "Error updating record: " . mysqli_error($conn);
            }
        }

        $sql = "select oer_text_description, count(*) as theCount from mngt140cases C inner join tboertext L on L.text_id=C.oer_text where cites_to=0 group by oer_text_description;";
        $original_case_counts = mysqli_query($conn, $sql);

        $sql = "select subject_matter_keywords, count(*) as theCount from mngt140cases C inner join tboertext L on L.text_id=C.oer_text where cites_to=0 group by subject_matter_keywords order by subject_matter_keywords;";
        $found_cases = mysqli_query($conn, $sql);

        require("head.php");

        $sql = "select id, parties, citation, subject_matter_keywords, URL, cites_to, snippet, reviewed from mngt140cases order by subject_matter_keywords, parties;";
        $result = mysqli_query($conn, $sql);

        $nav=$return_to;
        require("list.php");
      }

}

?>
