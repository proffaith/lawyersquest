<?php

print("<table><tr><td>");

if (mysqli_num_rows($original_case_counts) > 0) {
  print("<table width=30%><tr><td>");
  print("<thead><th>OER Text</th><th>Original Cases Count</th></thead></td><td></td></tr>");

  while ($row = mysqli_fetch_assoc($original_case_counts)) {
    $wherefrom=$row['oer_text_description'];
    $theCount=$row['theCount'];


    print("<tr><td>".$wherefrom."</td><td>".$theCount."</td></tr>");

  }
  print("</table>");

} else {

    print("<table><tr><td></td></tr></table>");

  }

print("</td> <td>");

  print("<table width=70%><tr><td>
    <ul class='sm'>
      <li>Home</li>
        <ul class='sm'>
          <li><a href='index.php?nav=0'>All Cases</a></li>
        </ul>
      <li>Original Cases</li>
        <ul class='sm'>
          <li><a href='index.php?nav=1'>Original Cases in 140 OER</a></li>
          <li><a href='index.php?nav=5'>Original Cases in 207 OER</a></li>
          <li><a href='index.php?nav=6'>Original Cases in 217 OER</a></li>
        </ul>
      <li>Found Trial Court Cases</li>
        <ul class='sm'>
          <li><a href='index.php?nav=2'>New District Court Cases</a></li>
          <li><a href='index.php?nav=3'>New Appellate Opinions</a></li>
          <li><a href='index.php?nav=4'>Recent USC Opinions</a></li>
        </ul>
    </ul>
    </td>
  </tr>

</table>");

print("</td></tr></table>");

 ?>
